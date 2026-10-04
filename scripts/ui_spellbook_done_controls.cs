// Native Spellbook Done faces. Patch only the five reserved 80x22 PNG cells.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

public static class VantageSpellbookDoneControls {
    public const int AtlasWidth=512, AtlasHeight=256;
    public const int Left=380, Top=24, Width=80, Height=22, StateStride=24;
    const int Samples=8;
    const double Radius=4.5, Inset=0.25, RimWidth=0.75;

    static double Distance(double x,double y,double inset,double radius) {
        double qx=Math.Abs(x-Width/2.0)-(Width/2.0-inset-radius);
        double qy=Math.Abs(y-Height/2.0)-(Height/2.0-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static int Coverage(int x,int y,double inset,double radius) {
        int inside=0;
        for(int sy=0;sy<Samples;sy++) for(int sx=0;sx<Samples;sx++)
            if(Distance(x+(sx+0.5)/Samples,y+(sy+0.5)/Samples,inset,radius)<=0)
                inside++;
        return (255*inside+Samples*Samples/2)/(Samples*Samples);
    }
    static Color Pixel(int x,int y,int state) {
        int alpha=Coverage(x,y,Inset,Radius);
        if(alpha==0) return Color.FromArgb(0,0,0,0);
        int inner=Coverage(x,y,Inset+RimWidth,Radius-RimWidth);
        bool down=state==2 || state==3, hover=state==1 || state==3;
        double t=(y+0.5)/Height;
        double face=down ? 17+10*t : 31-13*t+3*Math.Exp(-Math.Pow((t-0.2)/0.18,2));
        if(hover) face+=7;
        if(state==4) face=16-3*t;
        // A precise 0.75px coverage ring supplies warm structure; the face stays
        // graphite, with brighter flyby and reversed pressed depth.
        double strength=state==4 ? 0.23 : hover ? 0.78 : down ? 0.54 : 0.64;
        double rim=Math.Max(0,alpha-inner)/(double)alpha*strength;
        return Color.FromArgb(alpha,
            (int)Math.Round(face*(1-rim)+158*rim),
            (int)Math.Round(face*(1-rim)+131*rim),
            (int)Math.Round(face*(1-rim)+75*rim));
    }
    public static void Render(string destination) {
        if(Path.GetFileName(destination)!="spellbook_modern.png")
            throw new ArgumentException("Only the Spellbook PNG atlas is supported.");
        byte[] encoded;
        // Edit the decoded bitmap directly: drawing/cloning could premultiply
        // hidden RGB, changing protected pixels even where alpha is zero.
        using(var atlas=new Bitmap(destination)) {
            if(atlas.RawFormat.Guid!=ImageFormat.Png.Guid
                || atlas.Width!=AtlasWidth || atlas.Height!=AtlasHeight)
                throw new ArgumentException("Expected the reviewed 512x256 PNG atlas.");
            bool changed=false;
            for(int state=0;state<5;state++)
                for(int y=0;y<Height;y++) for(int x=0;x<Width;x++) {
                    int px=Left+x, py=Top+StateStride*state+y;
                    Color expected=Pixel(x,y,state);
                    if(atlas.GetPixel(px,py).ToArgb()==expected.ToArgb()) continue;
                    atlas.SetPixel(px,py,expected);
                    changed=true;
                }
            // Avoid encoder metadata drift when the decoded faces already
            // match, so repeating the patch preserves the PNG byte for byte.
            if(!changed) return;
            using(var output=new MemoryStream()) {
                atlas.Save(output,ImageFormat.Png);
                encoded=output.ToArray();
            }
        }
        File.WriteAllBytes(destination,encoded);
    }
}

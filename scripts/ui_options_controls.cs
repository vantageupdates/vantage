// Options-only button cells at their native dimensions, with clear toggle
// states. No settings, native binding, or shared control artwork is changed.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

public static class VantageOptionsControls {
    public static readonly int[,] Cells={{2,2,150,18,22},{156,2,150,16,22},
        {310,2,50,22,26},{2,124,150,20,24},{364,2,26,22,26}};
    static double Distance(double x,double y,int w,int h,double radius,double inset) {
        double qx=Math.Abs(x-w/2.0)-(w/2.0-inset-radius);
        double qy=Math.Abs(y-h/2.0)-(h/2.0-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static int Coverage(int x,int y,int w,int h) {
        int count=0;
        for(int sy=0;sy<8;sy++) for(int sx=0;sx<8;sx++)
            if(Distance(x+(sx+.5)/8,y+(sy+.5)/8,w,h,5,.5)<=0) count++;
        return (255*count+32)/64;
    }
    public static void Render(string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageOptionsControls.tga")
            throw new ArgumentException("Only the Options atlas is supported.");
        using(var atlas=new Bitmap(512,256,PixelFormat.Format32bppArgb)) {
            for(int n=0;n<Cells.GetLength(0);n++) for(int state=0;state<5;state++) {
                int w=Cells[n,2],h=Cells[n,3];
                for(int y=0;y<h;y++) for(int x=0;x<w;x++) {
                    int alpha=Coverage(x,y,w,h);
                    if(alpha==0) continue;
                    bool down=state==2 || state==3, hover=state==1 || state==3;
                    double t=(y+.5)/h;
                    double tone=down ? 39+4*t : 28-11*t+6*Math.Exp(-Math.Pow((t-.22)/.2,2));
                    if(hover) tone+=7;
                    if(state==4) tone=15+3*(1-t);
                    double depth=Math.Max(0,-Distance(x+.5,y+.5,w,h,5,.5));
                    // Depressed toggles keep a visible continuous gold ring,
                    // not just a color change or transient hover feedback.
                    double rim=(down?.8:hover?.48:.28)*Math.Exp(-Math.Pow(depth/.6,2));
                    var color=Color.FromArgb(alpha,(int)Math.Round(tone*(1-rim)+171*rim),
                        (int)Math.Round(tone*(1-rim)+147*rim),(int)Math.Round(tone*(1-rim)+94*rim));
                    atlas.SetPixel(Cells[n,0]+x,Cells[n,1]+state*Cells[n,4]+y,color);
                }
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2; header[13]=2;
                header[15]=1; header[16]=32; header[17]=40; output.Write(header);
                for(int y=0;y<256;y++) for(int x=0;x<512;x++) {
                    var c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
            if(!String.IsNullOrEmpty(preview)) atlas.Save(preview,ImageFormat.Png);
        }
    }
}

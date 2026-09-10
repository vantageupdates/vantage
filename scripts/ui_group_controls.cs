// Group-only native button faces: match hit boxes without stretching shared art.
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;

public static class VantageGroupControls {
    static double Distance(double x,double y,double inset) {
        double radius=4-inset;
        double qx=Math.Abs(x-32)-(32-inset-radius);
        double qy=Math.Abs(y-8)-(8-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static double Coverage(int x,int y,double inset) {
        int count=0;
        for(int sy=0;sy<8;sy++)for(int sx=0;sx<8;sx++)
            if(Distance(x+(sx+.5)/8,y+(sy+.5)/8,inset)<=0)count++;
        return count/64.0;
    }
    public static void Render(string destination,string preview) {
        if(Path.GetFileName(destination)!="VantageGroupControls.tga")
            throw new ArgumentException("Only the dedicated Group control atlas is supported.");
        using(var atlas=new Bitmap(128,128,PixelFormat.Format32bppArgb)) {
            // Normal, flyby, pressed, pressed-flyby, disabled.
            for(int state=0;state<5;state++)for(int y=0;y<16;y++)for(int x=0;x<64;x++) {
                double a=Coverage(x,y,.25);if(a==0)continue;
                double edge=(a-Coverage(x,y,1))/a,t=(y+.5)/16;
                bool down=state==2||state==3,hover=state==1||state==3;
                double face=down?18+11*t:32-14*t+3*Math.Exp(-Math.Pow((t-.2)/.18,2));
                if(hover)face+=7;
                if(state==4)face=18-3*t;
                double rim=edge*(state==4?.12:hover?.38:down?.28:.23);
                int tone=(int)Math.Round(face*(1-rim)+255*rim);
                atlas.SetPixel(2+x,2+20*state+y,Color.FromArgb((int)Math.Round(a*255),tone,tone,tone));
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                var header=new byte[18];header[2]=2;header[12]=128;header[14]=128;
                header[16]=32;header[17]=40;output.Write(header);
                for(int y=0;y<128;y++)for(int x=0;x<128;x++) {
                    var c=atlas.GetPixel(x,y);output.Write(c.B);output.Write(c.G);output.Write(c.R);output.Write(c.A);
                }
            }
            if(!String.IsNullOrEmpty(preview))atlas.Save(preview,ImageFormat.Png);
        }
    }
}

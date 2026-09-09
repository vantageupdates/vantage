// Mechanical packing of the generated stat sprites; no painted replacements.
// Dedicated currency faces are code-native rounded controls, not coin artwork.
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
public static class VantageInventoryDetails {
 static void Save(Bitmap b,string target) {
  using(var w=new BinaryWriter(File.Create(target))) {
   var h=new byte[18];h[2]=2;h[12]=(byte)b.Width;h[13]=(byte)(b.Width>>8);
   h[14]=(byte)b.Height;h[15]=(byte)(b.Height>>8);h[16]=32;h[17]=40;w.Write(h);
   for(int y=0;y<b.Height;y++)for(int x=0;x<b.Width;x++) {
    var c=b.GetPixel(x,y);w.Write(c.B);w.Write(c.G);w.Write(c.R);w.Write(c.A);
   }
  }
 }
 public static void Icons(string source,string weightSource,string target,string preview) {
  if(Path.GetFileName(target)!="VantageStatIcons.tga")throw new ArgumentException("Dedicated atlas only");
  PackIcons(source,weightSource,target,preview,12);
 }
 public static void CompactIcons(string source,string weightSource,string target,string preview) {
  if(Path.GetFileName(target)!="VantageCompactStatIcons.tga")throw new ArgumentException("Dedicated compact atlas only");
  PackIcons(source,weightSource,target,preview,10);
 }
 static void PackIcons(string source,string weightSource,string target,string preview,int size) {
  float inset=(16-size)/2f;
  using(var s=new Bitmap(source))using(var atlas=new Bitmap(64,64)) {
   if(s.Width!=1448||s.Height!=1086)throw new ArgumentException("Expected approved 1448x1086 RGBA sheet");
   int[] rows={0,375,695,1086};
   using(var g=Graphics.FromImage(atlas)) {
    g.CompositingMode=CompositingMode.SourceCopy;
    g.InterpolationMode=InterpolationMode.HighQualityBicubic;g.PixelOffsetMode=PixelOffsetMode.HighQuality;
    for(int i=0;i<12;i++) {
     int col=i%4,row=i/4,left=(col+1)*362,top=rows[row+1],right=col*362,bottom=rows[row];
     for(int y=rows[row];y<rows[row+1];y++)for(int x=col*362;x<(col+1)*362;x++)
      if(s.GetPixel(x,y).A>=32){left=Math.Min(left,x);right=Math.Max(right,x);top=Math.Min(top,y);bottom=Math.Max(bottom,y);}
     if(right<=left||bottom<=top)throw new Exception("Missing sprite");
     int w=right-left+1,h=bottom-top+1;float scale=(size-1f)/Math.Max(w,h);
     // Preserve the generated alpha and aspect ratio, with a clear cell gutter.
     g.DrawImage(s,new RectangleF(col*16+inset+(size-w*scale)/2,row*16+inset+(size-h*scale)/2,w*scale,h*scale),
                 new RectangleF(left,top,w,h),GraphicsUnit.Pixel);
    }
    using(var weight=new Bitmap(weightSource)) {
     int l=weight.Width,t=weight.Height,r=0,b=0;
     for(int y=0;y<weight.Height;y++)for(int x=0;x<weight.Width;x++)
      if(weight.GetPixel(x,y).A>=32){l=Math.Min(l,x);r=Math.Max(r,x);t=Math.Min(t,y);b=Math.Max(b,y);}
     if(r<=l||b<=t||weight.GetPixel(0,0).A!=0)throw new Exception("Expected transparent weight sprite");
     float scale=(size-1f)/Math.Max(r-l+1,b-t+1),w=(r-l+1)*scale,h=(b-t+1)*scale;
     g.DrawImage(weight,new RectangleF(inset+(size-w)/2,48+inset+(size-h)/2,w,h),new RectangleF(l,t,r-l+1,b-t+1),GraphicsUnit.Pixel);
    }
   }
   Save(atlas,target);if(!String.IsNullOrEmpty(preview))atlas.Save(preview,ImageFormat.Png);
  }
 }
 static double Distance(double x,double y,double inset) {
  double radius=4-inset,qx=Math.Abs(x-23)-(23-inset-radius),qy=Math.Abs(y-11)-(11-inset-radius);
  return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))+Math.Min(Math.Max(qx,qy),0)-radius;
 }
 static double Coverage(int x,int y,double inset) {
  int n=0;for(int a=0;a<8;a++)for(int b=0;b<8;b++)if(Distance(x+(a+.5)/8,y+(b+.5)/8,inset)<=0)n++;
  return n/64.0;
 }
 public static void Money(string target,string preview) {
  if(Path.GetFileName(target)!="VantageMoneyControls.tga")throw new ArgumentException("Dedicated currency atlas only");
  using(var atlas=new Bitmap(64,128)) {
   for(int state=0;state<5;state++)for(int y=0;y<22;y++)for(int x=0;x<46;x++) {
    double a=Coverage(x,y,.25); if(a==0)continue;
    double rim=(a-Coverage(x,y,1))/a;
    int top=state==1?35:state==2?15:state==3?22:state==4?17:26;
    double face=top-(top-12)*y/21.0;
    double strength=state==1?.64:state==3?.66:state==4?.22:.39;
    double edge=rim*strength;
    atlas.SetPixel(x+2,y+2+state*25,Color.FromArgb((int)Math.Round(a*255),
     (int)Math.Round(face*(1-edge)+181*edge),(int)Math.Round(face*(1-edge)+162*edge),(int)Math.Round(face*(1-edge)+119*edge)));
   }
   Save(atlas,target);if(!String.IsNullOrEmpty(preview))atlas.Save(preview,ImageFormat.Png);
  }
 }
}
